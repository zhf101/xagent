"use client";

import { useI18n } from "@/contexts/i18n-context";
import {
  Play,
  Heart,
  Loader2,
} from "lucide-react";
import { useState, useEffect } from "react";
import { cn, getApiUrl } from "@/lib/utils";
import { useRouter } from "next/navigation";
import { apiRequest } from "@/lib/api-wrapper";
import { SearchInput } from "@/components/ui/search-input";
import type { Template } from "@/types/template";

// Category section types
interface CategorySection {
  id: string;
  title: string;
  templates: Template[];
}

export default function TemplatesPage() {
  const { t, locale } = useI18n();
  const router = useRouter();
  const [selectedCategory, setSelectedCategory] = useState("All");
  const [searchQuery, setSearchQuery] = useState("");
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);

  const categories = [
    { id: "All", label: t("templates.categoryTitles.all") },
    { id: "Featured", label: t("templates.categoryTitles.featured") },
    {
      id: "Healthcare & Fitness",
      label: t("templates.categoryTitles.healthcare_fitness"),
    },
    {
      id: "General & Productivity",
      label: t("templates.categoryTitles.general_productivity"),
    },
    {
      id: "Customer Service",
      label: t("templates.categoryTitles.customer_service"),
    },
    {
      id: "Finance, LMS & Ops",
      label: t("templates.categoryTitles.finance_lms_ops"),
    },
    { id: "Security", label: t("templates.categoryTitles.security") },
  ];

  // Category display configuration
  const categoryConfig: Record<string, { title: string }> = {
    Featured: {
      title: t("templates.categoryTitles.featured"),
    },
    "Healthcare & Fitness": {
      title: t("templates.categoryTitles.healthcare_fitness"),
    },
    "General & Productivity": {
      title: t("templates.categoryTitles.general_productivity"),
    },
    "Customer Service": {
      title: t("templates.categoryTitles.customer_service"),
    },
    "Finance, LMS & Ops": {
      title: t("templates.categoryTitles.finance_lms_ops"),
    },
    Security: {
      title: t("templates.categoryTitles.security"),
    },
  };

  // Fetch templates from API
  useEffect(() => {
    const fetchTemplates = async () => {
      try {
        setLoading(true);
        const response = await apiRequest(
          `${getApiUrl()}/api/templates/?lang=${locale}`
        );
        if (response.ok) {
          const data = await response.json();
          setTemplates(data);
        }
      } catch (error) {
        console.error("Failed to fetch templates:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchTemplates();
  }, [locale]);

  // Group templates by category
  const groupTemplatesByCategory = (
    templatesList: Template[],
    includeFeaturedSection: boolean,
    includeCategorySections: boolean,
  ): CategorySection[] => {
    const grouped: Record<string, Template[]> = {};

    templatesList.forEach((template) => {
      if (includeFeaturedSection && template.featured) {
        if (!grouped.Featured) {
          grouped.Featured = [];
        }
        grouped.Featured.push(template);
      }
      if (!includeCategorySections) {
        return;
      }
      if (!grouped[template.category]) {
        grouped[template.category] = [];
      }
      grouped[template.category].push(template);
    });

    return Object.entries(grouped)
      .map(([category, templates]) => ({
        id: category.toLowerCase().replace(/\s+/g, "-"),
        title: categoryConfig[category]?.title || category,
        templates,
      }))
      .sort((a, b) => {
        if (a.title === t("templates.categoryTitles.featured")) {
          return -1;
        }
        if (b.title === t("templates.categoryTitles.featured")) {
          return 1;
        }
        return a.title.localeCompare(b.title);
      });
  };

  // Filter and group templates
  const filteredTemplates = templates.filter((template) => {
    const matchesCategory =
      selectedCategory === "All" ||
      (selectedCategory === "Featured" && Boolean(template.featured)) ||
      template.category === selectedCategory;
    const matchesSearch =
      template.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      template.description.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesCategory && matchesSearch;
  });

  const filteredSections = groupTemplatesByCategory(
    filteredTemplates,
    true,
    selectedCategory !== "Featured",
  );

  // Handle use template
  const handleUseTemplate = async (templateId: string) => {
    // Record usage
    try {
      await apiRequest(`${getApiUrl()}/api/templates/${templateId}/use`, {
        method: "POST",
      });
    } catch (error) {
      console.error("Failed to record template usage:", error);
    }

    // Navigate to build/new page with template parameter
    router.push(`/build/new?template=${templateId}`);
  };

  // Handle like template
  const handleLikeTemplate = async (
    templateId: string,
    e: React.MouseEvent,
  ) => {
    e.stopPropagation();
    try {
      const response = await apiRequest(
        `${getApiUrl()}/api/templates/${templateId}/like`,
        { method: "POST" },
      );
      if (response.ok) {
        // Refresh templates to get updated stats
        const templatesResponse = await apiRequest(
          `${getApiUrl()}/api/templates/?lang=${locale}`,
        );
        if (templatesResponse.ok) {
          const data = await templatesResponse.json();
          setTemplates(data);
        }
      }
    } catch (error) {
      console.error("Failed to like template:", error);
    }
  };

  return (
    <div className="flex flex-col h-full bg-background">
      {/* Header */}
      <div className="flex justify-between items-start w-full p-8">
        <div>
          <h1 className="text-3xl font-bold mb-1">{t("templates.title")}</h1>
          <p className="text-muted-foreground">{t("templates.subtitle")}</p>
        </div>
        <SearchInput
          placeholder={t("templates.searchPlaceholder")}
          value={searchQuery}
          onChange={setSearchQuery}
          containerClassName="w-72"
          className="bg-white border-border focus:border-primary/50 transition-all"
        />
      </div>

      {/* Category Filter */}
      <div className="w-full px-8 pb-6 flex gap-2 overflow-x-auto scrollbar-hide">
        {categories.map((category) => (
          <button
            key={category.id}
            onClick={() => setSelectedCategory(category.id)}
            className={cn(
              "px-4 py-1.5 rounded-full text-sm font-medium transition-all whitespace-nowrap",
              selectedCategory === category.id
                ? "bg-primary text-white shadow-sm"
                : "bg-white border border-border text-muted-foreground hover:border-primary/30 hover:text-foreground",
            )}
          >
            {category.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="w-full px-8 py-8 space-y-10">
            {filteredSections.map((section) => (
              <div key={section.id} className="animate-fade-in">
                {/* Section Header */}
                <div className="gap-2 mb-4 text-foreground/90 font-medium">
                  <h2>{section.title}</h2>
                </div>

                {/* Templates Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-5 gap-4">
                  {section.templates.map((template) => {
                    return (
                      <div
                        key={template.id}
                        onClick={() => handleUseTemplate(template.id)}
                        className="cursor-pointer shadow-sm p-5 rounded-xl border border-border/60 bg-white hover:border-primary/30 hover:shadow-md transition-all duration-200"
                      >
                        <h3 className="font-semibold text-base mb-2 group-hover:text-primary transition-colors">
                          {template.name}
                        </h3>
                        <p className="text-sm text-muted-foreground line-clamp-2 mb-4 h-10">
                          {template.description}
                        </p>

                        <div className="flex items-center justify-between text-xs text-muted-foreground mb-4">
                          <div className="flex items-center gap-3">
                            <div className="flex items-center gap-1">
                              <Play className="w-3 h-3 fill-current" />
                              <span>{template.used_count}</span>
                            </div>
                            <button
                              onClick={(e) =>
                                handleLikeTemplate(template.id, e)
                              }
                              className="flex items-center gap-1 hover:text-pink-500 transition-colors"
                            >
                              <Heart className="w-3 h-3 fill-current" />
                              <span>{template.likes}</span>
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}

            {filteredSections.length === 0 && !loading && (
              <div className="text-center py-20 text-muted-foreground">
                <p>{t("templates.noResults")}</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
