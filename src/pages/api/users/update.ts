import type { APIRoute } from "astro";
import { supabase } from "../../../lib/supabase";

export const POST: APIRoute = async ({ request }) => {
  // Check authorization
  const authHeader = request.headers.get("Authorization");
  if (!authHeader || !authHeader.startsWith("Bearer ")) {
    console.error("Authorization header missing or invalid", { authHeader });
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: {
        "Content-Type": "application/json",
      },
    });
  }

  // Extract the token
  const token = authHeader.split(" ")[1];

  try {
    // Get user data from request body
    const body = await request.json();
    const {
      userId,
      full_name,
      email,
      role,
      permissions,
      password,
      profile_pic_link,
      description,
      is_displayable,
      public_name,
    } = body;

    if (!userId) {
      return new Response(JSON.stringify({ error: "User ID is required" }), {
        status: 400,
        headers: {
          "Content-Type": "application/json",
        },
      });
    }

    // Check if the current user is admin
    // First verify the token by getting the user
    const {
      data: { user: tokenUser },
      error: tokenError,
    } = await supabase.auth.getUser(token);

    if (tokenError || !tokenUser) {
      console.error("Token validation failed", { tokenError });
      return new Response(JSON.stringify({ error: "Invalid token" }), {
        status: 401,
        headers: {
          "Content-Type": "application/json",
        },
      });
    }

    const { data: adminProfile } = await supabase
      .from("profiles")
      .select("role")
      .eq("id", tokenUser.id)
      .single();

    if (!adminProfile || adminProfile.role !== "admin") {
      return new Response(
        JSON.stringify({ error: "Admin privileges required" }),
        {
          status: 403,
          headers: {
            "Content-Type": "application/json",
          },
        }
      );
    }

    // Update password if provided
    if (password) {
      const { error: passwordError } = await supabase.auth.admin.updateUserById(
        userId,
        { password }
      );

      if (passwordError) {
        console.error("Error updating password:", passwordError);
        return new Response(JSON.stringify({ error: passwordError.message }), {
          status: 500,
          headers: {
            "Content-Type": "application/json",
          },
        });
      }
    }

    // Prepare profile update data
    const updateData: Record<string, any> = {};
    if (full_name !== undefined) updateData.full_name = full_name;
    if (public_name !== undefined) updateData.public_name = public_name;

    // Make sure role is one of the allowed values
    if (role !== undefined) {
      // Validate that role is one of the allowed enum values
      if (
        ![
          "admin",
          "insegnante",
          "docente",
          "studente",
          "direttore",
          "redattore",
          "giornalista",
        ].includes(role)
      ) {
        return new Response(
          JSON.stringify({
            error: `Invalid role. Must be one of: admin, insegnante, docente, studente, direttore, redattore, giornalista`,
          }),
          {
            status: 400,
            headers: {
              "Content-Type": "application/json",
            },
          }
        );
      }
      updateData.role = role;
    }

    if (permissions !== undefined) updateData.permissions = permissions;
    if (profile_pic_link !== undefined)
      updateData.profile_pic_link = profile_pic_link;
    if (description !== undefined) updateData.description = description;
    if (email !== undefined) updateData.email = email;
    if (is_displayable !== undefined)
      updateData.is_displayable = is_displayable;

    // Log the update data for debugging
    console.log("API: Profile update data for user", userId, ":", updateData);

    // Only update profile if there are fields to update
    if (Object.keys(updateData).length > 0) {
      const { error: updateError } = await supabase
        .from("profiles")
        .update(updateData)
        .eq("id", userId);

      if (updateError) {
        console.error("Error updating profile:", updateError);
        return new Response(JSON.stringify({ error: updateError.message }), {
          status: 500,
          headers: {
            "Content-Type": "application/json",
          },
        });
      }
    }

    return new Response(
      JSON.stringify({
        success: true,
        message: "User updated successfully",
      }),
      {
        status: 200,
        headers: {
          "Content-Type": "application/json",
        },
      }
    );
  } catch (error) {
    console.error("Error in update user endpoint:", error);
    return new Response(
      JSON.stringify({
        error: error instanceof Error ? error.message : "Unknown error",
      }),
      {
        status: 500,
        headers: {
          "Content-Type": "application/json",
        },
      }
    );
  }
};
